import os
import sys
import math
import json
import scipy
import random
import numpy as np
import PIL
from PIL import Image
import collections
import torch
import transforms3d
import itertools
import torchvision
import torchvision.transforms as T
from skimage import io, transform
from torchvision.transforms import functional as F

if sys.version_info < (3, 3):
    Sequence = collections.Sequence
    Iterable = collections.Iterable
else:
    Sequence = collections.abc.Sequence
    Iterable = collections.abc.Iterable
from pathlib import Path

lib_dir = (Path(__file__).parent / '..').resolve()
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))
from data.synset import synset as raw_synset


##############
# Helper fns #
##############

def read_json(file_path):
    with open(file_path) as json_file:
        data = json.load(json_file)
    return data


#######################
# Image transform fns #
#######################

_pil_interpolation_to_str = {
    Image.NEAREST: 'PIL.Image.NEAREST',
    Image.BILINEAR: 'PIL.Image.BILINEAR',
    Image.BICUBIC: 'PIL.Image.BICUBIC',
    Image.LANCZOS: 'PIL.Image.LANCZOS',
    Image.HAMMING: 'PIL.Image.HAMMING',
    Image.BOX: 'PIL.Image.BOX',
}

TASK_NAMES = ["autoencoder",
              "class_object",
              "class_scene",
              "normal",
              "jigsaw",
              "room_layout",
              "segmentsemantic"]


class Compose(T.Compose):
    def __init__(self, task_name, transforms):
        self.transforms = transforms
        self.task_name = task_name
        assert task_name in TASK_NAMES

    def __call__(self, sample):
        for t in self.transforms:
            sample = t(sample, self.task_name)
        return sample


class Cutout(object):

    def __init__(self, length):
        self.length = int(length)

    def cutout(self, img):
        h, w = img.size(1), img.size(2)
        mask = np.ones((h, w), np.float32)
        y = np.random.randint(h)
        x = np.random.randint(w)

        y1 = np.clip(y - self.length // 2, 0, h)
        y2 = np.clip(y + self.length // 2, 0, h)
        x1 = np.clip(x - self.length // 2, 0, w)
        x2 = np.clip(x + self.length // 2, 0, w)

        mask[y1: y2, x1: x2] = 0.
        mask = torch.from_numpy(mask)
        mask = mask.expand_as(img)
        img *= mask
        return img

    def __repr__(self):
        return '{name}(length={length})'.format(name=self.__class__.__name__, **self.__dict__)

    def __call__(self, sample, task_name):
        image, label = sample['image'], sample['label']
        if task_name in ['class_object', 'class_scene', 'room_layout']:
            return {'image': self.cutout(image),
                    'label': label}
        else:
            raise ValueError(f'task name {task_name} not available!')


class Resize(T.Resize):

    def __init__(self, input_size, target_size=None, interpolation=Image.BILINEAR):
        assert isinstance(input_size, int) or (isinstance(input_size, Iterable) and len(input_size) == 2)
        if target_size:
            assert isinstance(target_size, int) or (isinstance(target_size, Iterable) and len(target_size) == 2)
        self.input_size = input_size
        self.target_size = target_size if target_size is not None else input_size
        self.interpolation = interpolation

    def __call__(self, sample, task_name):
        """
        Args:
            img (PIL Image): Image to be scaled.

        Returns:
            PIL Image: Rescaled image.
        """
        image, label = sample['image'], sample['label']

        if task_name in ["autoencoder", "normal"]:
            return {'image': F.resize(image, self.input_size, self.interpolation),
                    'label': F.resize(label, self.target_size, self.interpolation)}
        elif task_name == "segmentsemantic":
            return {'image': F.resize(image, self.input_size, self.interpolation),
                    'label': F.resize(label, self.target_size, Image.NEAREST)}
        elif task_name in ['class_object', 'class_scene', 'room_layout', "jigsaw"]:
            return {'image': F.resize(image, self.input_size, self.interpolation),
                    'label': label}
        else:
            raise ValueError(f'task name {task_name} not available!')

    def __repr__(self):
        interpolate_str = _pil_interpolation_to_str[self.interpolation]
        return self.__class__.__name__ + '(input_size={0}, target_size={1}, interpolation={2})'.format(
            self.input_size, self.target_size, interpolate_str)


class ToPILImage(T.ToPILImage):

    def __init__(self, mode=None):
        self.mode = mode

    def __call__(self, sample, task_name):
        """
        Args:
            sample (Tensor or numpy.ndarray): {'image': image_to_convert, 'label': npy/png label}

        Returns:
            PIL Image: Image converted to PIL Image.

        """
        image, label = sample['image'], sample['label']
        if task_name in ["autoencoder", "normal"]:
            return {'image': F.to_pil_image(image, self.mode),
                    'label': F.to_pil_image(label, self.mode)}
        elif task_name == 'segmentsemantic':
            return {'image': F.to_pil_image(image, self.mode),
                    'label': F.to_pil_image(label, self.mode)}
        elif task_name in ['class_object', 'class_scene', 'room_layout', "jigsaw"]:
            return {'image': F.to_pil_image(image, self.mode),
                    'label': label}
        else:
            raise ValueError(f'task name {task_name} not available!')


class ToTensor(T.ToTensor):

    def __init__(self, new_scale=None):
        self.new_scale = new_scale

    def __call__(self, sample, task_name):
        """
        Args:
            pic (PIL Image or numpy.ndarray): Image to be converted to tensor.

        Returns:
            Tensor: Converted image.
        """
        image, label = sample['image'], sample['label']
        if task_name in ["autoencoder", "normal"]:
            image = F.to_tensor(image).float()
            label = F.to_tensor(label).float()
            if self.new_scale:
                min_val, max_val = self.new_scale
                label *= (max_val - min_val)
                label += min_val
        elif task_name == 'segmentsemantic':
            image = F.to_tensor(image).float()
            label = torch.tensor(np.array(label), dtype=torch.uint8)
        elif task_name in ['class_object', 'class_scene', 'room_layout']:
            image = F.to_tensor(image).float()
            label = torch.FloatTensor(label)
        else:
            raise ValueError(f'task name {task_name} not available!')
        if self.new_scale:
            min_val, max_val = self.new_scale
            image *= (max_val - min_val)
            image += min_val
        return {'image': image, 'label': label}


class Normalize(T.Normalize):

    def __init__(self, mean, std, inplace=False):
        self.mean = mean
        self.std = std
        self.inplace = inplace

    def __call__(self, sample, task_name):
        """
        Args:
            tensor (Tensor): Tensor image of size (C, H, W) to be normalized.

        Returns:
            Tensor: Normalized Tensor image.
        """
        tensor, label = sample['image'], sample['label']
        # if task_name in ["segmentsemantic"]:
        #     raise TypeError("['segmentsemantic'] cannot apply normalize")
        if task_name in ["autoencoder"]:
            return {'image': F.normalize(tensor, self.mean, self.std, self.inplace),
                    'label': F.normalize(label, self.mean, self.std, self.inplace)}
        elif task_name in ["normal", 'segmentsemantic']:
            return {'image': F.normalize(tensor, self.mean, self.std, self.inplace),
                    'label': label}
        elif task_name in ['class_object', 'class_scene', 'room_layout']:
            return {'image': F.normalize(tensor, self.mean, self.std, self.inplace),
                    'label': label}
        else:
            raise ValueError(f'task name {task_name} not available!')


class RandomHorizontalFlip(T.RandomHorizontalFlip):
    """Horizontally flip the given PIL Image randomly with a given probability.

    Args:
        p (float): probability of the image being flipped. Default value is 0.5
    """

    def __init__(self, p=0.5):
        self.p = p

    def __call__(self, sample, task_name):
        """
        Args:
            img (PIL Image): Image to be flipped.

        Returns:
            PIL Image: Randomly flipped image.
        """
        random_num = random.random()
        image, label = sample['image'], sample['label']
        if random_num < self.p:
            if task_name in ["autoencoder", 'segmentsemantic']:
                return {'image': F.hflip(image),
                        'label': F.hflip(label)}
            elif task_name in ['class_object', 'class_scene', "jigsaw"]:
                return {'image': F.hflip(image),
                        'label': label}
            elif task_name in ['normal', 'room_layout']:
                raise ValueError(f'task name {task_name} not available!')
            else:
                raise ValueError(f'task name {task_name} not available!')
        else:
            return sample


class RandomGrayscale(T.RandomGrayscale):
    """Randomly convert image to grayscale with a probability of p (default 0.1).

    Args:
        p (float): probability that image should be converted to grayscale.

    Returns:
        PIL Image: Grayscale version of the input image with probability p and unchanged
        with probability (1-p).
        - If input image is 1 channel: grayscale version is 1 channel
        - If input image is 3 channel: grayscale version is 3 channel with r == g == b

    """

    def __init__(self, p=0.1):
        self.p = p

    def __call__(self, sample, task_name):
        """
        Args:
            img (PIL Image): Image to be converted to grayscale.

        Returns:
            PIL Image: Randomly grayscaled image.
        """
        image, label = sample['image'], sample['label']
        num_output_channels = 1 if image.mode == 'L' else 3
        if random.random() < self.p:
            if task_name in ["jigsaw"]:
                return {'image': F.to_grayscale(image, num_output_channels=num_output_channels),
                        'label': label}
            else:
                raise ValueError(f'task name {task_name} not available!')
        else:
            return sample


class ColorJitter(T.ColorJitter):
    def __init__(self, brightness=0, contrast=0, saturation=0, hue=0):
        self.brightness = self._check_input(brightness, 'brightness')
        self.contrast = self._check_input(contrast, 'contrast')
        self.saturation = self._check_input(saturation, 'saturation')
        self.hue = self._check_input(hue, 'hue', center=0, bound=(-0.5, 0.5),
                                     clip_first_on_zero=False)

    def __call__(self, sample, task_name):
        t = self.get_params(self.brightness, self.contrast,
                            self.saturation, self.hue)
        image, label = sample['image'], sample['label']
        if task_name in ['autoencoder']:
            return {'image': t(image),
                    'label': t(label)}
        elif task_name == 'segmentsemantic':
            return {'image': t(image),
                    'label': label}
        elif task_name in ['class_object', 'class_scene', 'room_layout', 'normal', "jigsaw"]:
            return {'image': t(image),
                    'label': label}
        else:
            raise ValueError(f'task name {task_name} not available!')


########################
# Classification Tasks #
########################

def np_softmax(logits):
    maxs = np.amax(logits, axis=-1)
    softmax = np.exp(logits - np.expand_dims(maxs, axis=-1))
    sums = np.sum(softmax, axis=-1)
    softmax = softmax / np.expand_dims(sums, -1)
    return softmax


def load_class_object_logits(label_path, selected=False, normalize=True, final5k=False):
    """
    Class 1000 ImageNet Ground Truth
    :param label_path: path to a specific label file
    :param selected: original taskonomy data: 1000 cls -> 100 cls
    :param final5k: transnas-bench data: 100 cls -> 75 cls
    :param normalize: normalize the remaining 75 cls label (sum to be 1.0)
    :return: target: the target probability (returned as np.array with dim=(1000/100/75,))
    """
    try:
        logits = np.load(label_path)
    except:
        print(f'corrupted: {label_path}!')
        raise
    lib_data_dir = os.path.abspath(os.path.dirname(__file__))
    if selected:  # original taskonomy data: 1000 cls -> 100 cls
        selection_file = os.path.join(lib_data_dir, 'class_object_final5k.npy') if final5k else \
            os.path.join(lib_data_dir, 'class_object_selected.npy')
        selection = np.load(selection_file)
        logits = logits[selection.astype(bool)]
        if normalize:
            logits = logits / logits.sum()
    target = np.asarray(logits)
    return target


def load_class_object_label(label_path, selected=False, final5k=False):
    """
    Class 1000 ImageNet Ground Truth
    :param label_path: path to a specific label file
    :param selected: original taskonomy data: 1000 cls -> 100 cls
    :param final5k: transnas-bench data: 100 cls -> 75 cls
    :return: target: the target label (returned as np.array with dim=(1,))
    """
    logits = load_class_object_logits(label_path, selected=selected, normalize=False, final5k=final5k)
    target = np.asarray(logits.argmax())
    return target


def load_class_scene_logits(label_path, selected=False, normalize=True, final5k=False):
    """
    Class Scene Ground Truth
    :param label_path: path to a specific label file
    :param selected: original taskonomy data: 365 cls -> 63 cls
    :param final5k: transnas-bench data: 63 cls -> 47 cls
    :param normalize: normalize the remaining 47 cls label (sum to be 1.0)
    :return: target: the target probability (returned as np.array with dim=(365/63/47,))
    """
    try:
        logits = np.load(label_path)
    except:
        raise FileNotFoundError(f'corrupted: {label_path}!')
    lib_data_dir = os.path.abspath(os.path.dirname(__file__))
    if selected:
        selection_file = os.path.join(lib_data_dir, 'class_scene_final5k.npy') if final5k else \
            os.path.join(lib_data_dir, 'class_scene_selected.npy')
        selection = np.load(selection_file)
        logits = logits[selection.astype(bool)]
        if normalize:
            logits = logits / logits.sum()
    target = np.asarray(logits)
    return target


def load_class_scene_label(label_path, selected=False, final5k=False):
    """
    Class Scene Ground Truth
    :param label_path: path to a specific label file
    :param selected: original taskonomy data: 365 cls -> 63 cls
    :param final5k: transnas-bench data: 63 cls -> 47 cls
    :return: target: the target label (returned as np.array with dim=(1,))
    """
    logits = load_class_scene_logits(label_path, selected=selected, normalize=False, final5k=final5k)
    target = np.asarray(logits.argmax())
    return target


def get_synset(task, selected=True, final5k=False):
    """
    Get class names for classification tasks
    :param task: task in ['class_object', 'class_scene']
    :param selected: original taskonomy data with reduced classes
    :param final5k: transnas-bench data with reduced classes
    :return:
    """
    if task == 'class_scene':
        selection_file = 'class_scene_final5k.npy' if final5k else 'class_scene_selected.npy'
        selection = np.load((Path(__file__).parent / selection_file).resolve())
        with open((Path(__file__).parent / 'class_scene_names.json').resolve(), 'r') as fp:
            synset_scene = [x[3:] for x in json.load(fp)]
            if selected:
                synset_scene = [x for x, y in zip(synset_scene, selection) if y == 1.]
        synset = synset_scene
    elif task == 'class_object':
        synset_object = [" ".join(i.split(" ")[1:]) for i in raw_synset]
        selection_file = 'class_object_final5k.npy' if final5k else 'class_object_selected.npy'
        selection = np.load((Path(__file__).parent / selection_file).resolve())
        if selected:
            synset_object = [x for x, y in zip(synset_object, selection) if y == 1.]
        synset = synset_object
    else:
        raise ValueError(f"{task} not in ['class_object', 'class_scene'], cannot get_synset")
    return synset


#####################################
# Room Layout (code from taskonomy) #
#####################################

def get_camera_rot_matrix(view_dict, flip_xy=False):
    return get_camera_matrix(view_dict, flip_xy=flip_xy)[:3, :3]


def rotate_world_to_cam(points, view_dict):
    cam_mat = get_camera_rot_matrix(view_dict, flip_xy=True)
    new_points = cam_mat.T.dot(points).T[:, :3]
    return new_points


def get_camera_matrix(view_dict, flip_xy=False):
    position = view_dict['camera_location']
    rotation_euler = view_dict['camera_rotation_final']
    R = transforms3d.euler.euler2mat(*rotation_euler, axes='sxyz')
    camera_matrix = transforms3d.affines.compose(position, R, np.ones(3))

    if flip_xy:
        # For some reason the x and y are flipped in room layout
        temp = np.copy(camera_matrix[0, :])
        camera_matrix[0, :] = camera_matrix[1, :]
        camera_matrix[1, :] = -temp
    return camera_matrix


def get_room_layout_cam_mat_and_ranges(view_dict, make_x_major=False):
    # Get BB information
    bbox_ranges = view_dict['bounding_box_ranges']
    # BB seem to be off w.r.t. the camera matrix
    ranges = [bbox_ranges['x'], -np.array(bbox_ranges['y'])[::-1], bbox_ranges['z']]

    camera_matrix = get_camera_matrix(view_dict, flip_xy=True)
    if not make_x_major:
        return camera_matrix, ranges
    # print(world_points[:,-1])
    # print(view_dict['camera_location'])
    axes_xyz = np.eye(3)
    apply_90_deg_rot_k_times = [
        transforms3d.axangles.axangle2mat(axes_xyz[-1], k * math.pi / 2)
        for k in range(4)]

    def make_world_x_major(view_dictx):
        """ Rotates the world coords so that the -z direction of the camera
            is within 45-degrees of the global +x axis """
        global_x = np.array([axes_xyz[0]]).T
        best = (180., "Nothing")
        for world_rotx in apply_90_deg_rot_k_times:
            global_x_in_cam = rotate_world_to_cam(
                world_rotx.dot(global_x), view_dictx)
            # Project onto camera's horizontal (xz) plane
            degrees_away = math.degrees(
                math.acos(np.dot(global_x_in_cam, -axes_xyz[2]))
            )
            best = min(best, (degrees_away, np.linalg.inv(world_rotx)))  # python is neat
            # if abs(degrees_away) < 45.:
            #     return np.linalg.inv(world_rot)
        return best[-1]

    def update_ranges(world_rotx, rangesx):
        new_ranges = np.dot(world_rotx, rangesx)
        for i, rng in enumerate(new_ranges):  # make sure rng[0] < rng[1]
            if rng[0] > rng[1]:
                new_ranges[i] = [rng[1], rng[0]]
        return new_ranges

    world_rot = np.zeros((4, 4))
    world_rot[3, 3] = 1.
    world_rot[:3, :3] = make_world_x_major(view_dict)
    ranges = update_ranges(world_rot[:3, :3], ranges)
    camera_matrix = np.dot(world_rot, camera_matrix)
    return camera_matrix, ranges


def point_info2room_layout(label_path):
    """
    Room Bounding Box.
    Returns:
    --------
        bb: length 6 vector
    """

    try:
        with open(label_path) as fp:
            data = json.load(fp)
    except:
        print(f'corrupted: {json_file}!')
        raise

    def homogenize(M):
        return np.concatenate([M, np.ones((M.shape[0], 1))], axis=1)

    def convert_world_to_cam(points, cam_mat=None):
        new_points = points.T
        homogenized_points = homogenize(new_points)
        new_points = np.dot(homogenized_points, np.linalg.inv(cam_mat).T)[:, :3]
        return new_points

    mean = np.array([-1.64378987e-02, 7.03680296e-02, -2.72496318e+00,
                     1.56155458e+00, -2.83141191e-04, -1.57136446e+00,
                     4.81219593e+00, 3.69077521e+00, 2.61998101e+00])
    std = np.array([0.73644884, 0.53726124, 1.45194796,
                    0.19338562, 0.01549811, 0.42258508,
                    2.80763433, 1.92678054, 0.89655357])

    camera_matrix, bb = get_room_layout_cam_mat_and_ranges(data, make_x_major=True)
    camera_matrix_euler = transforms3d.euler.mat2euler(camera_matrix[:3, :3], axes='sxyz')
    vertices = np.array(list(itertools.product(*bb)))
    vertices_cam = convert_world_to_cam(vertices.T, camera_matrix)
    cube_center = np.mean(vertices_cam, axis=0)

    x_scale, y_scale, z_scale = bb[:, 1] - bb[:, 0]  # maxes - mins
    bbox_cam = np.hstack(
        (cube_center,
         camera_matrix_euler,
         x_scale, y_scale, z_scale))
    bbox_cam = (bbox_cam - mean) / std
    return bbox_cam


def room_layout(label_path):
    try:
        bbox_cam = np.load(label_path)
    except:
        raise Exception(f'corrupted: {label_path}!')
    return bbox_cam


########################
# Autoencoder & Normal #
########################

def load_raw_img_label(label_path):
    try:
        image = io.imread(label_path)
    except:
        raise Exception(f'corrupted: {label_path}!')
    return image


################
# Segmentation #
################

def semantic_segment_label(label_path):
    """
    Segmentation

    Returns:
    --------
        pixels: size num_pixels x 3 numpy array
    """
    try:
        label = io.imread(label_path)
    except:
        raise Exception(f'corrupted: {label_path}!')
    label[label == 0] = 1
    label = label - 1

    return label


##########
# jigsaw #
##########

def random_jigsaw_permutation(label_path, classes=1000):
    rand_ind = random.randint(0, classes - 1)
    return rand_ind


def get_permutation_set(mode, classes=1000):
    assert mode in ['max', 'avg']
    permutation_path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                    f'permutations_hamming_{mode}_{classes}.npy')
    return np.load(permutation_path)


def image2tiles(img, permutation, new_dims):
    """
    Generate the 9 pieces input for Jigsaw task. (added tile gaps & chromatic aberration)

    Parameters:
    -----------
        img (PIL Image): Image to be cropped (3, 255, 255)

    Return:
    -----------
        img_tiles: 9 PIL image pieces
    """

    if len(permutation) != 9:
        raise ValueError(f'Target permutation of Jigsaw is supposed to have lenght 9, getting {len(permutation)} here')

    He, Wi = img.size  # (255, 255)

    unitH = int(He / 3)  # 85
    unitW = int(Wi / 3)  # 85

    endH = new_dims[0]  # 64
    endW = new_dims[1]  # 64

    img_tiles = []

    for n in range(9):
        pos = permutation[n]
        posH = int(pos // 3) * unitH
        posW = int(pos % 3) * unitW
        pos_i = torch.randint(0, unitH - endH + 1, size=(1,)).item()
        pos_j = torch.randint(0, unitW - endW + 1, size=(1,)).item()
        img_tiles.append(F.crop(img, posH + pos_i, posW + pos_j, endH, endW))

    return img_tiles


class MakeJigsawPuzzle(object):
    def __init__(self, classes, mode, tile_dim=(64, 64), centercrop=None, norm=True, totensor=True):
        self.classes = classes
        self.mode = mode  # ['max', 'avg']
        self.permutation_set = get_permutation_set(classes=classes, mode=mode)
        self.tile_dim = tile_dim
        self.centercrop = centercrop  # float
        self.image_norm = norm  # normalize separate images
        self.totensor = totensor

    def __call__(self, sample, task_name):
        """
        Jigsaw Puzzle input function, separate a (C, 255, 255) image into (9, C, 64, 64) images
        Inputs:
            image: as type PIL image (3, 255, 255)

        Returns:
        ----------
            img: (9, 3, 64, 64) images
            label: class_index
        """
        assert task_name == 'jigsaw'
        image, permutation_idx = sample['image'], sample['label']
        permutation = self.permutation_set[permutation_idx]
        if task_name == "jigsaw":
            He, Wi = image.size  # (255, 255)
            if self.centercrop:
                image = F.center_crop(image, (He * self.centercrop, Wi * self.centercrop))
                image = F.resize(image, (He, Wi), Image.BILINEAR)

            pil_image_tiles = image2tiles(image, permutation, self.tile_dim)
            if self.totensor:
                raws = torch.empty((9, 3, self.tile_dim[0], self.tile_dim[1]), dtype=torch.float32)
                images = torch.empty((9, 3, self.tile_dim[0], self.tile_dim[1]), dtype=torch.float32)
                for i, tile in enumerate(pil_image_tiles):
                    tile_tensor = F.to_tensor(tile)
                    raws[i, :, :, :] = tile_tensor
                    if self.image_norm:
                        mean = tile_tensor.mean((-2, -1))
                        std = tile_tensor.std((-2, -1)) + 0.0001
                        tile_tensor = F.normalize(tile_tensor, mean, std)
                    images[i, :, :, :] = tile_tensor
            else:
                raws = pil_image_tiles
                images = pil_image_tiles

            return {'raw': raws,
                    'image': images,
                    'label': permutation_idx}
        else:
            raise TypeError("Only jigsaw can use MakeJigsawPuzzle")
